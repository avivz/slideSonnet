// Plain-DOM view for the playback controller: the stage overlay (the playing
// slide, drawn over the stage while the editor is on another one). Framework-
// free: it is plain DOM driven per animation frame, which is cheaper than
// re-rendering components 60 times a second.
import type { Frame } from './controller'

/** Holds the playing slide's picture over a stage element when the frame asks for it. */
export class StageOverlay {
  readonly root: HTMLDivElement
  private readonly img: HTMLImageElement
  private src: string | null = null

  constructor(stage: HTMLElement) {
    const existing = stage.querySelector<HTMLDivElement>(':scope > .ss-overlay')
    if (existing) existing.remove() // a previous controller's overlay
    this.root = document.createElement('div')
    this.root.className = 'ss-overlay'
    this.img = document.createElement('img')
    this.img.alt = ''
    this.root.append(this.img)
    stage.appendChild(this.root)
  }

  render(frame: Frame): void {
    if (!frame.loaded || frame.imageUrl === null) {
      this.hide()
      return
    }
    if (frame.imageUrl !== this.src) {
      this.img.src = frame.imageUrl
      this.src = frame.imageUrl
    }
    this.root.classList.add('ss-on')
  }

  hide(): void {
    this.root.classList.remove('ss-on')
  }

  dispose(): void {
    this.root.remove()
  }
}
