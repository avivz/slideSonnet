// Plain-DOM views for the playback controller: the stage overlay (the playing
// slide plus transitions, drawn over the stage) and the transport (scrubber +
// time label). Framework-free: the stage overlay is plain DOM driven per
// animation frame, which is cheaper than re-rendering components 60 times a second.
import { formatClock } from './cues'
import type { Frame } from './controller'
import type { LayerStyle } from './morph'

const UNSET = Symbol('unset')

/**
 * Draws the playing slide and any transition over a stage element.
 *
 * When a transition lands, the picture taking over (the still layer, or the
 * stage's own image in a single-slide preview) may not be painted yet — a
 * picture mid-load shows nothing, or the slide before. So the handoff waits for
 * that picture to decode, not for a timer; until then the transition's incoming
 * layer stays up.
 */
export class StageOverlay {
  readonly root: HTMLDivElement
  private readonly a: HTMLImageElement
  private readonly b: HTMLImageElement
  private srcA: string | null | typeof UNSET = UNSET
  private srcB: string | null | typeof UNSET = UNSET
  /** A transition has landed; the picture taking over isn't known to be painted. */
  private handoff = false
  private last: Frame | null = null
  /** Per image: the src it has decoded, and the src it is decoding. */
  private readonly decoded = new WeakMap<HTMLImageElement, string>()
  private readonly decoding = new WeakMap<HTMLImageElement, string>()

  constructor(private readonly stage: HTMLElement) {
    const existing = stage.querySelector<HTMLDivElement>(':scope > .ss-morph')
    if (existing) existing.remove() // a previous controller's overlay
    this.root = document.createElement('div')
    this.root.className = 'ss-morph'
    this.a = document.createElement('img')
    this.b = document.createElement('img')
    this.a.alt = ''
    this.b.alt = ''
    this.root.append(this.a, this.b)
    stage.appendChild(this.root)
  }

  render(frame: Frame): void {
    this.last = frame
    if (!frame.loaded) {
      this.hide()
      return
    }
    if (frame.morph !== null) {
      this.root.classList.add('ss-on')
      this.root.setAttribute('data-morph', '') // a transition is drawing
      this.root.style.background = frame.morph.background
      this.srcA = this.layer(this.a, frame.morph.a, this.srcA)
      this.srcB = this.layer(this.b, frame.morph.b, this.srcB)
      this.handoff = true
      return
    }
    this.root.removeAttribute('data-morph')
    if (frame.imageUrl === null) {
      // a single-slide preview: between transitions the stage's own image shows the slide
      const under = this.stage.querySelector<HTMLImageElement>(':scope > img')
      if (this.handoff && under !== null && !this.painted(under)) this.holdIncoming()
      else this.hide()
      return
    }
    // no transition: the playing slide, still
    this.root.classList.add('ss-on')
    const still: LayerStyle = { src: frame.imageUrl, opacity: 1, transform: '', clipPath: '', zIndex: 1 }
    this.srcA = this.layer(this.a, still, this.srcA)
    if (this.handoff && !this.painted(this.a)) {
      this.holdIncoming()
      return
    }
    this.handoff = false
    this.root.style.background = ''
    this.srcB = this.layer(this.b, { ...still, opacity: 0, zIndex: 2 }, this.srcB)
  }

  hide(): void {
    this.handoff = false
    this.root.classList.remove('ss-on')
    this.root.removeAttribute('data-morph')
    for (const layer of [this.a, this.b]) {
      layer.style.opacity = ''
      layer.style.transform = ''
      layer.style.clipPath = ''
      layer.style.zIndex = ''
    }
  }

  dispose(): void {
    this.last = null
    this.root.remove()
  }

  /** The landed transition's incoming layer, whole and on top, as it last showed. */
  private holdIncoming(): void {
    this.root.classList.add('ss-on')
    this.root.style.background = ''
    const src = this.srcB === UNSET ? null : this.srcB
    this.srcB = this.layer(this.b, { src, opacity: 1, transform: '', clipPath: '', zIndex: 2 }, this.srcB)
  }

  /** Has `img` decoded its current picture? If not, decodes it and redraws once it has. */
  private painted(img: HTMLImageElement): boolean {
    const src = img.src
    if (!src || this.decoded.get(img) === src) return true
    if (typeof img.decode !== 'function') return true // can't tell: don't hold
    if (this.decoding.get(img) !== src) {
      this.decoding.set(img, src)
      const settle = (): void => {
        this.decoded.set(img, src) // a broken picture too: never hold on it forever
        if (img.src === src && this.last !== null) this.render(this.last)
      }
      img.decode().then(settle, settle)
    }
    return false
  }

  private layer(img: HTMLImageElement, style: LayerStyle, prev: string | null | typeof UNSET) {
    if (style.src !== prev) {
      if (style.src) {
        img.src = style.src
        img.style.background = ''
      } else {
        img.removeAttribute('src')
        img.style.background = '#000' // no neighbour slide: morph against black
      }
    }
    img.style.opacity = String(style.opacity)
    img.style.transform = style.transform
    img.style.clipPath = style.clipPath
    img.style.zIndex = String(style.zIndex)
    return style.src
  }
}

/** The scrubber and the `0:12 / 1:40` label. Seeking never waits on the server. */
export class Transport {
  readonly root: HTMLDivElement
  private readonly range: HTMLInputElement
  private readonly label: HTMLSpanElement
  private scrubbing = false
  private duration = 0

  constructor(host: HTMLElement, onSeekFraction: (fraction: number) => void) {
    host.querySelector(':scope > .ss-transport')?.remove()
    this.root = document.createElement('div')
    this.root.className = 'ss-transport'
    this.range = document.createElement('input')
    this.range.type = 'range'
    this.range.min = '0'
    this.range.max = '1000'
    this.range.value = '0'
    this.range.disabled = true
    this.range.className = 'ss-scrub'
    this.range.setAttribute('aria-label', 'Playback position')
    this.label = document.createElement('span')
    this.label.className = 'ss-time'
    this.range.addEventListener('pointerdown', () => {
      this.scrubbing = true
    })
    this.range.addEventListener('input', () => {
      const fraction = Number(this.range.value) / 1000
      this.label.textContent = this.clock(fraction * this.duration)
    })
    this.range.addEventListener('change', () => {
      this.scrubbing = false
      onSeekFraction(Number(this.range.value) / 1000) // one seek per scrub, on release
    })
    this.root.append(this.range, this.label)
    host.appendChild(this.root)
  }

  render(frame: Frame): void {
    this.duration = frame.duration
    this.range.disabled = !frame.loaded
    if (!frame.loaded) {
      this.range.value = '0'
      this.label.textContent = ''
      return
    }
    if (!this.scrubbing) {
      const fraction = frame.duration > 0 ? frame.time / frame.duration : 0
      this.range.value = String(Math.round(Math.min(1, fraction) * 1000))
      this.label.textContent = this.clock(frame.time)
    }
  }

  dispose(): void {
    this.root.remove()
  }

  private clock(t: number): string {
    return `${formatClock(t)} / ${formatClock(this.duration)}`
  }
}
