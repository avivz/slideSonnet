// The preview manifest the server returns for a built preview (see
// server/previews.py::PreviewManifest). Everything the browser needs to play
// one slide's track on its own clock: the immutable track and where each
// spoken line plays in it.

/** Where one utterance plays in the track (seconds). */
export interface SpeechSpan {
  slide_id: string
  /** The utterance's position among the slide's spoken lines. */
  index: number
  start: number
  end: number
  /** The silent stretches inside it (a breath, a clip's tail), absolute times. */
  silences: [number, number][]
}

export interface PreviewManifest {
  artifact_id: string
  /** The slide this track plays. */
  slide_id: string
  narration_revision: string
  pdf_revision: string
  engine: string | null
  media_url: string
  duration: number
  /** Every utterance's span, for following the spoken word. */
  speech: SpeechSpan[]
}
