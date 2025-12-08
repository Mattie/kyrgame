export type GemstoneTheme = {
  name: string
  emoji: string
  lightColor: string
  darkColor: string
}

export const GEMSTONE_THEMES: Record<string, GemstoneTheme> = {
  ruby: { name: 'ruby', emoji: '❤️', lightColor: '#f87171', darkColor: '#7f1d1d' },
  emerald: { name: 'emerald', emoji: '🍀', lightColor: '#34d399', darkColor: '#065f46' },
  garnet: { name: 'garnet', emoji: '🍒', lightColor: '#fb7185', darkColor: '#831843' },
  pearl: { name: 'pearl', emoji: '🦪', lightColor: '#f8fafc', darkColor: '#94a3b8' },
  aquamarine: { name: 'aquamarine', emoji: '💧', lightColor: '#67e8f9', darkColor: '#0ea5e9' },
  moonstone: { name: 'moonstone', emoji: '🌙', lightColor: '#e0e7ff', darkColor: '#312e81' },
  sapphire: { name: 'sapphire', emoji: '🔷', lightColor: '#60a5fa', darkColor: '#1e3a8a' },
  diamond: { name: 'diamond', emoji: '💎', lightColor: '#e2e8f0', darkColor: '#0f172a' },
  amethyst: { name: 'amethyst', emoji: '🪻', lightColor: '#c084fc', darkColor: '#6b21a8' },
  onyx: { name: 'onyx', emoji: '🖤', lightColor: '#4b5563', darkColor: '#0b0f19' },
  opal: { name: 'opal', emoji: '🌈', lightColor: '#fde68a', darkColor: '#7c2d12' },
  bloodstone: { name: 'bloodstone', emoji: '🩸', lightColor: '#fca5a5', darkColor: '#991b1b' },
}

export const getGemstoneTheme = (name: string | null | undefined): GemstoneTheme | undefined => {
  if (!name) return undefined
  return GEMSTONE_THEMES[name.toLowerCase()]
}
