// How an engine is named to the user ("Kokoro", not the config key "kokoro").
const LABELS: Record<string, string> = { kokoro: 'Kokoro', inworld: 'Inworld', qwen3: 'Qwen3' }

export function engineLabel(name: string | null | undefined): string {
  if (!name) return 'the default engine'
  return LABELS[name] ?? name.charAt(0).toUpperCase() + name.slice(1)
}
