import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { expect, it } from 'vitest'

import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useConfirm } from '@/stores/confirm'

it('asks a second question after the first is answered, never dropping either', async () => {
  document.body.innerHTML = ''
  setActivePinia(createPinia())
  const w = mount(ConfirmDialog, { attachTo: document.body })
  const first = useConfirm().ask({ title: 'Spend credits?', lines: [], yes: 'Generate' })
  const second = useConfirm().ask({ title: 'Export a draft?', lines: [], yes: 'Export draft' })
  await flushPromises()
  expect(document.body.textContent).toContain('Spend credits?')
  document.querySelector<HTMLButtonElement>('[data-testid="confirm-yes"]')?.click()
  expect(await first).toBe(true)
  await flushPromises()
  expect(document.body.textContent).toContain('Export a draft?')
  const cancel = [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Cancel')
  cancel?.click()
  expect(await second).toBe(false)
  w.unmount()
})
