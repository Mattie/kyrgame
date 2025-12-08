type GemstoneName =
  | 'ruby'
  | 'emerald'
  | 'garnet'
  | 'pearl'
  | 'aquamarine'
  | 'moonstone'
  | 'sapphire'
  | 'diamond'
  | 'amethyst'
  | 'onyx'
  | 'opal'
  | 'bloodstone'
  | 'kyragem'
  | 'soulstone'

export type GemstoneVisual = {
  name: GemstoneName
  emoji: string
  lightColor: string
  darkColor: string
  displayName?: string
}

const formatDisplayName = (name: string): string =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(' ')

export const gemstonePalette: Record<GemstoneName, GemstoneVisual> = {
  ruby: {
    name: 'ruby',
    emoji: '🔴',
    lightColor: '#ff6b6b',
    darkColor: '#7b1b1b',
  },
  emerald: {
    name: 'emerald',
    emoji: '🟢',
    lightColor: '#34d399',
    darkColor: '#065f46',
  },
  garnet: {
    name: 'garnet',
    emoji: '🟠',
    lightColor: '#d8395f',
    darkColor: '#5b0f1e',
  },
  pearl: {
    name: 'pearl',
    emoji: '⚪',
    lightColor: '#f5f3ff',
    darkColor: '#6b7280',
  },
  aquamarine: {
    name: 'aquamarine',
    emoji: '🔷',
    lightColor: '#67e8f9',
    darkColor: '#0ea5e9',
  },
  moonstone: {
    name: 'moonstone',
    emoji: '🌕',
    lightColor: '#e5e7eb',
    darkColor: '#111827',
  },
  sapphire: {
    name: 'sapphire',
    emoji: '🔵',
    lightColor: '#3b82f6',
    darkColor: '#1e3a8a',
  },
  diamond: {
    name: 'diamond',
    emoji: '💎',
    lightColor: '#e0f2fe',
    darkColor: '#0f172a',
  },
  amethyst: {
    name: 'amethyst',
    emoji: '🟣',
    lightColor: '#c084fc',
    darkColor: '#6b21a8',
  },
  onyx: {
    name: 'onyx',
    emoji: '⚫',
    lightColor: '#9ca3af',
    darkColor: '#0b0f10',
  },
  opal: {
    name: 'opal',
    emoji: '🔮',
    lightColor: '#fce7f3',
    darkColor: '#3f2a2f',
  },
  bloodstone: {
    name: 'bloodstone',
    emoji: '🟤',
    lightColor: '#fca5a5',
    darkColor: '#7f1d1d',
  },
  kyragem: {
    name: 'kyragem',
    emoji: '⭐',
    lightColor: '#fde68a',
    darkColor: '#92400e',
  },
  soulstone: {
    name: 'soulstone',
    emoji: '💠',
    lightColor: '#c7d2fe',
    darkColor: '#312e81',
  },
}

export const getGemstoneVisual = (
  name: string
): (GemstoneVisual & { displayName: string }) | null => {
  const key = name.toLowerCase() as GemstoneName
  const visual = gemstonePalette[key]
  if (!visual) return null
  const displayName = visual.displayName ?? formatDisplayName(visual.name)
  return { ...visual, displayName }
}

export const formatGemstoneLabel = (name: string): string => {
  const visual = getGemstoneVisual(name)
  const displayName = visual?.displayName ?? formatDisplayName(name)
  return visual ? `${visual.emoji} ${displayName}` : displayName
}
