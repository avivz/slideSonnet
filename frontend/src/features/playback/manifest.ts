// The preview manifest the server returns for a built preview (see
// server/previews.py::PreviewManifest). Everything the browser needs to play a
// preview on its own clock: the immutable track, its cue sheet, page images,
// and the transition schedule. Browser visuals approximate the export; the
// FFmpeg render stays authoritative.

export interface Cue {
  start: number
  slide_id: string
}

export interface PageImage {
  slide_id: string
  image_url: string | null
}

/** One transition: completes at `at`, running `dur` seconds before it. */
export interface MorphStep {
  at: number
  dur: number
  kind: string
  /** Outgoing image, or null for a black frame (the deck's first slide). */
  from: string | null
  /** Incoming image, or null for a black frame (the deck's last slide). */
  to: string | null
}

export interface PreviewManifest {
  artifact_id: string
  /** The slide a single-slide preview plays, or null for the whole deck. */
  slide_id: string | null
  narration_revision: string
  pdf_revision: string
  engine: string | null
  media_url: string
  duration: number
  start_at: number
  cues: Cue[]
  pages: PageImage[]
  transitions: MorphStep[]
}
