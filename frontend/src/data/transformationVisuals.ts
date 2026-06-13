export const unseenForceTextShadow =
  '0 0 6px rgba(255,255,255,0.57), 0 0 14px rgba(255,228,241,0.45)'

const transformationVisualEntries = [
  {
    aliases: ['Some Unseen Force', 'Unseen Force'],
    emoji: '👻',
    color: '#ffe4f1',
    className: 'form-unseen-force',
    textShadow: unseenForceTextShadow,
  },
  {
    aliases: ['Some pegasus', 'pegasus'],
    emoji: '🪽',
    color: '#ffffff',
    className: 'form-pegasus',
  },
  {
    // Legacy messages use both "psuedo" in form state and "puesdo" in S24M00/S24M01.
    aliases: [
      'Some psuedo dragon',
      'psuedo dragon',
      'Some puesdo dragon',
      'puesdo dragon',
      'Some pseudo dragon',
      'pseudo dragon',
    ],
    emoji: '🐉',
    color: '#b6402b',
    className: 'form-pseudo-dragon',
  },
  {
    aliases: ['Some willowisp', 'willowisp'],
    emoji: '✨',
    color: '#facc15',
    className: 'form-willowisp',
  },
] as const

export type TransformationVisual = {
  emoji: string
  color: string
  className: string
  textShadow?: string
}

export const transformationVisualAliases = transformationVisualEntries.flatMap(
  (entry) => entry.aliases
)

const transformationVisualsByAlias = Object.fromEntries(
  transformationVisualEntries.flatMap((entry) =>
    entry.aliases.map((alias) => [alias.toLowerCase(), entry])
  )
)

export const getTransformationVisual = (name: string): TransformationVisual | null => {
  const visual = transformationVisualsByAlias[name.trim().toLowerCase()]
  if (!visual) return null

  const result: TransformationVisual = {
    emoji: visual.emoji,
    color: visual.color,
    className: visual.className,
  }
  if ('textShadow' in visual) {
    result.textShadow = visual.textShadow
  }
  return result
}
