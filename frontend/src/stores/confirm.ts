// The editor's one yes/no question at a time: anything may ask (a paid
// generation, an export draft, resetting the comparison); ConfirmDialog shows
// it. Questions asked while one is open wait their turn, and every one gets an
// answer — true only on an explicit yes.
import { defineStore } from 'pinia'
import { shallowRef } from 'vue'

export interface Question {
  title: string
  lines: string[]
  yes: string
  danger?: boolean
}

export const useConfirm = defineStore('confirm', () => {
  const shown = shallowRef<Question | null>(null)
  let settle: (ok: boolean) => void = () => {}
  const waiting: { question: Question; resolve: (ok: boolean) => void }[] = []

  function showNext(): void {
    const next = waiting.shift()
    shown.value = next?.question ?? null
    settle = next?.resolve ?? (() => {})
  }

  function ask(question: Question): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
      waiting.push({ question, resolve })
      if (shown.value === null) showNext()
    })
  }

  /** The dialog's answer to the question shown. */
  function answer(ok: boolean): void {
    if (shown.value === null) return
    const reply = settle
    showNext()
    reply(ok)
  }

  return { shown, ask, answer }
})
