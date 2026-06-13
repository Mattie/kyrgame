export const groundObjectVisuals = {
  scroll: {
    name: 'scroll',
    emoji: '📜',
    color: '#f6c96d',
    darkColor: '#72450f',
    className: 'object-scroll',
  },
  elixir: {
    name: 'elixir',
    emoji: '🧪',
    color: '#76c923',
    darkColor: '#155e75',
    className: 'object-elixir',
  },
  codex: {
    name: 'codex',
    emoji: '📖',
    color: '#c084fc',
    darkColor: '#581c87',
    className: 'object-codex',
  },
  tome: {
    name: 'tome',
    emoji: '📖',
    color: '#c084fc',
    darkColor: '#581c87',
    className: 'object-tome',
  },
  parchment: {
    name: 'parchment',
    emoji: '📜',
    color: '#f6c96d',
    darkColor: '#72450f',
    className: 'object-parchment',
  },
  pinecone: {
    name: 'pinecone',
    emoji: '🌰',
    color: '#d4a373',
    darkColor: '#5f3217',
    className: 'object-pinecone',
  },
} as const

export type GroundObjectVisualName = keyof typeof groundObjectVisuals
export type GroundObjectVisual =
  (typeof groundObjectVisuals)[GroundObjectVisualName] & {
    displayName: string
  }

const isGroundObjectVisualName = (value: string): value is GroundObjectVisualName =>
  Object.prototype.hasOwnProperty.call(groundObjectVisuals, value)

const normalizeGroundObjectVisualName = (name: string): GroundObjectVisualName | null => {
  const normalized = name.trim().toLowerCase()
  if (isGroundObjectVisualName(normalized)) return normalized

  const singular = normalized.endsWith('s') ? normalized.slice(0, -1) : normalized
  return isGroundObjectVisualName(singular) ? singular : null
}

export const groundObjectVisualAliases = (
  Object.keys(groundObjectVisuals) as GroundObjectVisualName[]
).flatMap((name) => [name, `${name}s`])

export const getGroundObjectVisual = (name: string): GroundObjectVisual | null => {
  const key = normalizeGroundObjectVisualName(name)
  if (!key) return null

  const visual = groundObjectVisuals[key]
  return { ...visual, displayName: visual.name }
}
