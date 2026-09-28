// Entry point for hosting the playback controller inside the NiceGUI editor
// (Phase 3 of the migration). Built to a stable path, /ui/embed/playback.js,
// which the editor page loads as a module. The Python side keeps owning the
// <audio> element's source and the play/pause buttons; this module owns the
// clock-driven visuals and tells the page only when the playing slide changes,
// by dispatching an `ssslide` event (detail: slide id) on the audio element.
import { PlaybackController } from './controller'
import { StageOverlay, Transport } from './dom'
import type { PreviewManifest } from './manifest'

export interface Mount {
  /** Id of the element holding the <audio> (NiceGUI's `c<id>`), or of the audio itself. */
  audioId: string
  /** Id of the stage element the overlay draws over. */
  stageId: string
  /** Id of the element the scrubber and time label go in. */
  transportId: string
}

interface Instance {
  audio: HTMLAudioElement
  controller: PlaybackController
  overlay: StageOverlay
  transport: Transport
}

const instances = new Map<string, Instance>()

function findAudio(id: string): HTMLAudioElement | null {
  const el = document.getElementById(id)
  if (!el) return null
  return el instanceof HTMLAudioElement ? el : el.querySelector('audio')
}

function instance(mount: Mount): Instance | null {
  const existing = instances.get(mount.audioId)
  const audio = findAudio(mount.audioId)
  if (existing && existing.audio === audio && existing.overlay.root.isConnected) return existing
  existing?.controller.dispose()
  existing?.overlay.dispose()
  existing?.transport.dispose()
  const stage = document.getElementById(mount.stageId)
  const host = document.getElementById(mount.transportId)
  if (!audio || !stage || !host) return null
  const overlay = new StageOverlay(stage)
  let transport: Transport | null = null
  const controller = new PlaybackController(audio, {
    onFrame: (frame) => {
      overlay.render(frame)
      transport?.render(frame)
    },
    onSlide: (slideId) => {
      audio.dispatchEvent(new CustomEvent('ssslide', { detail: slideId }))
    },
  })
  transport = new Transport(host, (fraction) => controller.seekFraction(fraction))
  const made = { audio, controller, overlay, transport }
  instances.set(mount.audioId, made)
  return made
}

function withInstance(mount: Mount, fn: (i: Instance) => void): void {
  const inst = instance(mount)
  if (inst) fn(inst)
}

export const api = {
  /** The page pointed the audio at `manifest.media_url`: take it over from here. */
  load(mount: Mount, manifest: PreviewManifest): void {
    withInstance(mount, (i) => i.controller.load(manifest))
  },
  play(mount: Mount): void {
    withInstance(mount, (i) => i.controller.play())
  },
  pause(mount: Mount): void {
    withInstance(mount, (i) => i.controller.pause())
  },
  stop(mount: Mount): void {
    withInstance(mount, (i) => i.controller.stop())
  },
  setRate(mount: Mount, rate: number): void {
    withInstance(mount, (i) => i.controller.setRate(rate))
  },
  seekToSlide(mount: Mount, slideId: string): void {
    withInstance(mount, (i) => i.controller.seekToSlide(slideId))
  },
}

declare global {
  interface Window {
    ssPlayback?: typeof api
  }
}

window.ssPlayback = api
