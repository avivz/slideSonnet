// Following the spoken word. Clip audio carries no word timings, so the word is
// estimated: within an utterance's span, time is shared out over its words in
// proportion to their length (the subtitles split long cues the same way).
// Close enough to read along; the audio stays the truth.
import type { SpeechSpan } from './manifest'

/** The utterance playing at `time` (seconds into the track), or null in a pause. */
export function spanAt(spans: readonly SpeechSpan[], time: number): SpeechSpan | null {
  return spans.find((s) => time >= s.start && time < s.end) ?? null
}

/** The line to go on from at `time`: the one playing, or the next; null past the last. */
export function lineAt(spans: readonly SpeechSpan[], time: number): number | null {
  return spans.find((s) => time < s.end)?.index ?? null
}

/**
 * How far through its words an utterance is at `time` (0..1), counting only
 * voiced time: the clock stands still through the silences inside the clip (a
 * breath at a comma, a clip's silent tail), so the words finish with the voice.
 */
export function voicedFraction(span: SpeechSpan, time: number): number {
  const t = Math.min(Math.max(time, span.start), span.end)
  let voiced = span.end - span.start
  let spoken = t - span.start
  for (const [a, b] of span.silences ?? []) { // none from a server before this change
    voiced -= b - a
    spoken -= Math.max(0, Math.min(b, t) - a)
  }
  return voiced > 0 ? Math.min(1, Math.max(0, spoken / voiced)) : 1
}

/** The `[start, end)` character range of the word at `fraction` (0..1) of `text`. */
export function wordAt(text: string, fraction: number): [number, number] | null {
  const words = [...text.matchAll(/\S+/g)]
  if (words.length === 0) return null
  // a word's share: its letters plus the breath after it
  const total = words.reduce((n, w) => n + w[0].length + 1, 0)
  let target = Math.min(Math.max(fraction, 0), 1) * total
  for (const w of words) {
    target -= w[0].length + 1
    if (target < 0) return [w.index, w.index + w[0].length]
  }
  const last = words[words.length - 1]
  return last ? [last.index, last.index + last[0].length] : null
}
