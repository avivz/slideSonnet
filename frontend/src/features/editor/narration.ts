// The editor's view of one slide's narration, as pure data.
//
// A saved block is a flat list of segments. The editor shows it as: the
// transition *into* the slide (really the boundary with the previous slide),
// a start silence, the utterance/pause cards, an end silence, and the
// transition *out*. The edge silences are only separate fields on a slide that
// speaks; a silent slide keeps its pauses as cards. (Ported from gui/state.py
// split_edge_silences / bracket_silences and gui/app.py BlockEditor.)
import type { BlockDTO, MetaDTO, SegmentDTO, TransitionDTO } from '@/api/client'

export type Pace = 'slow' | 'normal' | 'fast'

/** One card. `key` is browser-only identity (keeps focus across updates). */
export interface EditSeg {
  key: string
  kind: 'speech' | 'pause'
  text: string
  voice: string | null
  pace: Pace | null
  direction: string
  seconds: number
}

export interface EditBlock {
  slideId: string
  middle: EditSeg[]
  /** Start/end silence fields; null when the slide doesn't speak (no fields). */
  start: number | null
  end: number | null
  transitionIn: TransitionDTO
  transitionOut: TransitionDTO
}

export interface SilenceDefaults {
  start: number
  end: number
}

let nextKey = 0
export function newKey(): string {
  nextKey += 1
  return `seg-${nextKey}`
}

function toEdit(seg: SegmentDTO): EditSeg {
  if (seg.kind === 'pause') {
    return { key: newKey(), kind: 'pause', text: '', voice: null, pace: null, direction: '', seconds: seg.seconds }
  }
  return {
    key: newKey(),
    kind: 'speech',
    text: seg.text ?? '',
    voice: seg.voice ?? null,
    pace: seg.pace ?? null,
    direction: seg.direction ?? '',
    seconds: 0,
  }
}

export function speaks(segments: readonly { kind: string; text?: string | null }[]): boolean {
  return segments.some((s) => s.kind === 'speech' && (s.text ?? '').trim() !== '')
}

const CUT: TransitionDTO = { kind: 'cut', seconds: 0 }

/** The editable form of `block` (or an empty slide), given its incoming boundary. */
export function editBlock(
  slideId: string,
  block: BlockDTO | undefined,
  incoming: TransitionDTO,
  defaults: SilenceDefaults,
): EditBlock {
  const segments = block?.segments ?? []
  let middle = segments.map(toEdit)
  let start: number | null = null
  let end: number | null = null
  if (speaks(segments)) {
    start = defaults.start
    end = defaults.end
    if (middle.length > 0 && middle[0]?.kind === 'pause') {
      start = (middle[0] as EditSeg).seconds
      middle = middle.slice(1)
    }
    if (middle.length > 0 && middle.at(-1)?.kind === 'pause') {
      end = (middle.at(-1) as EditSeg).seconds
      middle = middle.slice(0, -1)
    }
  }
  return {
    slideId,
    middle,
    start,
    end,
    transitionIn: { ...incoming },
    transitionOut: block ? { ...block.transition_out } : { ...CUT },
  }
}

/** Whether the start/end silence fields are shown (and saved) for `block`. */
export function hasSilenceFields(block: EditBlock): boolean {
  return block.start !== null && block.end !== null
}

/** Show the silence fields once the slide starts speaking (at the deck defaults). */
export function syncSilenceFields(block: EditBlock, defaults: SilenceDefaults): void {
  if (!hasSilenceFields(block) && speaks(block.middle)) {
    block.start = defaults.start
    block.end = defaults.end
  }
}

function fromEdit(seg: EditSeg): SegmentDTO {
  if (seg.kind === 'pause') return { kind: 'pause', seconds: Math.max(0, seg.seconds) }
  return {
    kind: 'speech',
    text: seg.text,
    voice: seg.voice,
    pace: seg.pace === 'normal' ? null : seg.pace, // normal is the default: not written
    direction: seg.direction.trim() === '' ? null : seg.direction.trim(),
  }
}

/** The segments a save writes: the cards, bracketed by the silences when shown. */
export function blockSegments(block: EditBlock): SegmentDTO[] {
  const middle = block.middle.map(fromEdit)
  if (hasSilenceFields(block) && block.middle.some((s) => s.kind === 'speech')) {
    return [
      { kind: 'pause', seconds: Math.max(0, block.start ?? 0) },
      ...middle,
      { kind: 'pause', seconds: Math.max(0, block.end ?? 0) },
    ]
  }
  return middle
}

/** A stable fingerprint of what a save of `block` would write (dirty checks). */
export function fingerprint(block: EditBlock): string {
  return JSON.stringify([blockSegments(block), block.transitionIn, block.transitionOut])
}

export function newSpeech(): EditSeg {
  return { key: newKey(), kind: 'speech', text: '', voice: null, pace: null, direction: '', seconds: 0 }
}

export function newPause(): EditSeg {
  return { key: newKey(), kind: 'pause', text: '', voice: null, pace: null, direction: '', seconds: 1 }
}

export function moveSeg(block: EditBlock, index: number, delta: number): boolean {
  const j = index + delta
  if (index < 0 || j < 0 || index >= block.middle.length || j >= block.middle.length) return false
  const items = block.middle
  const a = items[index] as EditSeg
  items[index] = items[j] as EditSeg
  items[j] = a
  return true
}

/** Speech segments' positions: card index → speech index (for per-clip audio). */
export function speechIndexes(block: EditBlock): Map<string, number> {
  const out = new Map<string, number>()
  let n = 0
  for (const seg of block.middle) {
    if (seg.kind === 'speech') out.set(seg.key, n++)
  }
  return out
}

// ---- the transition gallery (family + direction pickers) -------------------------
export type Families = MetaDTO['transitions']

export function decompose(
  families: Families,
  aliases: Record<string, string>,
  kind: string,
): { family: string; direction: string | null } {
  const resolved = aliases[kind] ?? kind
  for (const f of families) {
    if (f.options.length === 0) {
      if (f.key === resolved) return { family: f.key, direction: null }
    } else {
      const hit = f.options.find(([, name]) => name === resolved)
      if (hit) return { family: f.key, direction: hit[0] }
    }
  }
  return { family: 'cut', direction: null }
}

export function compose(families: Families, family: string, direction: string | null): string {
  const f = families.find((x) => x.key === family)
  if (!f || f.options.length === 0) return f?.key ?? 'cut'
  const hit = f.options.find(([label]) => label === direction)
  return (hit ?? f.options[0])?.[1] ?? 'cut'
}

export function directionsFor(families: Families, family: string): string[] {
  return families.find((x) => x.key === family)?.options.map(([label]) => label) ?? []
}
